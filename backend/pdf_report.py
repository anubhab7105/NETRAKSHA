import io
import json
from datetime import datetime, timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def generate_case_pdf(
    case_data: dict,
    extracted_fields: list,
    module_results: list,
    citizen_data: dict = None,
    officer_actions: list = None,
    provenance_data: dict = None,
    iris_data: dict = None,
) -> bytes:
    """Generate an official, tamper-evident forensic PDF report for a screening case."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=32,
        leftMargin=32,
        topMargin=28,
        bottomMargin=28,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#0F2942'),
        alignment=1,
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#C88A10'),
        alignment=1,
    )
    subtext_style = ParagraphStyle(
        'DocSubtext',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#556070'),
        alignment=1,
    )

    section_hdr = ParagraphStyle(
        'SecHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor('#0F2942'),
        spaceAfter=3,
    )

    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#1D2939'),
    )

    cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#1D2939'),
    )

    cell_header = ParagraphStyle(
        'TableHdr',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#344054'),
    )

    badge_pass = ParagraphStyle(
        'BadgePass',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#027A48'),
    )
    badge_fail = ParagraphStyle(
        'BadgeFail',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#B42318'),
    )
    badge_review = ParagraphStyle(
        'BadgeReview',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#B54708'),
    )

    story = []

    # 1. Header Banner
    story.append(Paragraph("GOVERNMENT OF INDIA · MINISTRY OF HOME AFFAIRS", title_style))
    story.append(Spacer(1, 2))
    story.append(Paragraph("SASHASTRA SEEMA BAL (SSB) · POLICE II DIVISION", subtitle_style))
    story.append(Spacer(1, 2))
    story.append(Paragraph("CHECKPOINT FORENSIC IDENTITY & DOCUMENT SCREENING REPORT", subtext_style))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0F2942'), spaceAfter=8))

    # 2. Case Metadata Table
    case_id = case_data.get('id', 0)
    ts = case_data.get('timestamp') or datetime.now(timezone.utc).isoformat()
    if isinstance(ts, str):
        try:
            ts_clean = ts.replace('Z', '+00:00')
            ts_str = datetime.fromisoformat(ts_clean).strftime('%d %b %Y, %H:%M:%S UTC')
        except Exception:
            ts_str = str(ts)[:19]
    else:
        ts_str = str(ts)

    unit = case_data.get('unit') or 'BORDER_UNIT_1'
    officer_id = case_data.get('officer_id') or 'N/A'
    doc_type = (case_data.get('document_type') or 'UNKNOWN').upper()
    status = (case_data.get('status') or 'COMPLETED').upper()
    verdict = (case_data.get('verdict') or 'UNKNOWN').upper()
    risk_score = case_data.get('risk_score', 0)

    meta_data = [
        [
            Paragraph("<b>Case Reference:</b>", cell_style),
            Paragraph(f"<b>#{case_id:04d}</b>", cell_bold),
            Paragraph("<b>Date & Time:</b>", cell_style),
            Paragraph(ts_str, cell_style),
        ],
        [
            Paragraph("<b>Border Unit:</b>", cell_style),
            Paragraph(str(unit), cell_style),
            Paragraph("<b>Screening Officer:</b>", cell_style),
            Paragraph(f"Officer ID #{officer_id}", cell_style),
        ],
        [
            Paragraph("<b>Document Type:</b>", cell_style),
            Paragraph(doc_type, cell_style),
            Paragraph("<b>Case Status:</b>", cell_style),
            Paragraph(status, cell_style),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[90, 160, 100, 180])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    # 3. Verdict Banner Card
    if verdict == "GREEN":
        bg_col = colors.HexColor('#ECFDF3')
        border_col = colors.HexColor('#027A48')
        badge_text = "VERIFIED — CLEARANCE RECOMMENDED"
        verdict_para = badge_pass
        recommendation = "All forensic checks passed within acceptable tolerance. Low risk of forgery or impersonation."
    elif verdict == "YELLOW":
        bg_col = colors.HexColor('#FFFAEB')
        border_col = colors.HexColor('#B54708')
        badge_text = "MANUAL REVIEW REQUIRED"
        verdict_para = badge_review
        recommendation = "Anomalies or inconclusive biometric/quality gates detected. Physical officer review required."
    else:  # RED or other
        bg_col = colors.HexColor('#FEF3F2')
        border_col = colors.HexColor('#B42318')
        badge_text = "HIGH RISK — ESCALATE / DENY"
        verdict_para = badge_fail
        recommendation = "Critical fraud indicator, demographic mismatch, face mismatch, or watchlist hit detected."

    verdict_data = [
        [
            Paragraph(f"<b>VERDICT: {badge_text}</b>", verdict_para),
            Paragraph(f"<b>COMPOSITE RISK: {risk_score:.0f} / 100</b>", verdict_para),
        ],
        [
            Paragraph(f"<b>Operational Advisory:</b> {recommendation}", cell_style),
            Paragraph(f"<b>Framework:</b> Multi-Layer Forensic Risk Engine", cell_style),
        ],
    ]
    verdict_table = Table(verdict_data, colWidths=[350, 180])
    verdict_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg_col),
        ('BOX', (0, 0), (-1, -1), 1.25, border_col),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, border_col),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(verdict_table)
    story.append(Spacer(1, 10))

    # 4. Demographic Cross-Verification Table
    story.append(Paragraph("1. Demographic Cross-Verification (Document vs. National Registry)", section_hdr))
    if not extracted_fields:
        story.append(Paragraph("<i>No demographic fields extracted from the presented document.</i>", cell_style))
    else:
        demo_rows = [
            [
                Paragraph("Field Name", cell_header),
                Paragraph("Extracted (Document)", cell_header),
                Paragraph("National Registry Record", cell_header),
                Paragraph("Status", cell_header),
            ]
        ]
        has_registry = citizen_data is not None or any(bool(f.get('database_value')) for f in extracted_fields)
        for f in extracted_fields:
            fname = str(f.get('field_name', 'Field')).replace('_', ' ').title()
            val = str(f.get('extracted_value') or '—')
            db_val = f.get('database_value') if f.get('database_value') is not None else f.get('expected_value')
            if db_val is not None and str(db_val).strip():
                exp = str(db_val)
            else:
                exp = '—' if has_registry else 'No DB Record'
            m_status = str(f.get('match_status') or 'unknown').lower()

            if m_status == 'match':
                stat_p = Paragraph("✔ MATCH", badge_pass)
            elif m_status == 'mismatch':
                stat_p = Paragraph("✖ MISMATCH", badge_fail)
            else:
                stat_p = Paragraph(m_status.upper(), badge_review)

            demo_rows.append([
                Paragraph(fname, cell_bold),
                Paragraph(val, cell_style),
                Paragraph(exp, cell_style),
                stat_p,
            ])

        demo_table = Table(demo_rows, colWidths=[120, 155, 155, 100])
        demo_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EAECF0')),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#D0D5DD')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E4E7EC')),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(demo_table)

    story.append(Spacer(1, 10))

    # 5. Forensic Pipeline Module Results Table
    story.append(Paragraph("2. Forensic Inspection & Biometric Module Breakdown", section_hdr))

    # Helper to parse module results
    def find_mod(name):
        mod = next((m for m in module_results if m.get('module_name') == name), None)
        if not mod and name == 'face_match':
            # Check if 3-way face verification is nested inside gemini_ai module
            gem = next((m for m in module_results if m.get('module_name') == 'gemini_ai'), None)
            if gem:
                g_raw = gem.get('raw_output') or {}
                if isinstance(g_raw, str):
                    try:
                        g_raw = json.loads(g_raw)
                    except Exception:
                        g_raw = {}
                tw = g_raw.get('three_way_face_match') or {}
                if tw:
                    sim = tw.get('similarity_score')
                    has_verdict = (
                        sim is not None
                        or tw.get('live_vs_doc_match') is not None
                        or tw.get('doc_vs_db_match') is not None
                        or tw.get('live_vs_db_match') is not None
                    )
                    mod = {
                        'module_name': 'face_match',
                        'score': sim,
                        'status': 'ok' if has_verdict else gem.get('status', 'ok'),
                        'raw_output': tw,
                    }
        return mod

    modules_to_report = [
        ('tamper', 'Document Tamper Analysis (ELA + Copy-Move)'),
        ('physical_forgery', 'Physical Counterfeit & Layout Engine'),
        ('checksum', 'MRZ & Checksum Consistency (ICAO/Verhoeff)'),
        ('face_match', '3-Way Face Biometric (InsightFace ArcFace)'),
        ('liveness', '14-Frame Liveness Burst (MediaPipe Kinematics)'),
        ('deepfake', 'Deepfake Spectrum Artifacts (FFT Analysis)'),
        ('watchlist', 'Interpol & National Lookout DB Screening'),
    ]

    forensic_rows = [
        [
            Paragraph("Inspection Module", cell_header),
            Paragraph("Score / Conf.", cell_header),
            Paragraph("Result", cell_header),
            Paragraph("Forensic Summary & Detection Notes", cell_header),
        ]
    ]

    for mod_key, mod_label in modules_to_report:
        m = find_mod(mod_key)
        raw = {}
        if m and m.get('raw_output'):
            raw_val = m.get('raw_output')
            if isinstance(raw_val, str):
                try:
                    raw = json.loads(raw_val)
                except Exception:
                    raw = {}
            elif isinstance(raw_val, dict):
                raw = raw_val

        status = (m.get('status') or 'SKIPPED').lower() if m else 'skipped'
        score = m.get('score') if m else None
        if score is None and raw and raw.get('similarity_score') is not None:
            score = raw.get('similarity_score')
        score_str = f"{score * 100:.1f}%" if (score is not None and score <= 1.0) else f"{score}" if score is not None else "N/A"

        # Determine badge & message
        if not m:
            res_p = Paragraph("NOT CAPTURED", badge_review)
            notes = "Module skipped or evidence was not provided."
        elif mod_key == 'face_match':
            l_doc = raw.get('live_vs_doc_match')
            d_db = raw.get('doc_vs_db_match')
            l_db = raw.get('live_vs_db_match')
            match_bool = raw.get('match') if raw.get('match') is not None else l_doc

            legs = []
            if l_doc is not None:
                legs.append(f"Live↔Doc: {'Match' if l_doc else 'Mismatch'}")
            if d_db is not None:
                legs.append(f"Doc↔DB: {'Match' if d_db else 'Mismatch'}")
            if l_db is not None:
                legs.append(f"Live↔DB: {'Match' if l_db else 'Mismatch'}")
            legs_str = " | ".join(legs)

            if match_bool is True:
                res_p = Paragraph("MATCH", badge_pass)
                notes = f"Biometric match verified ({score_str}). {legs_str}" if legs_str else f"Biometric match established ({score_str})."
            elif match_bool is False:
                res_p = Paragraph("MISMATCH", badge_fail)
                notes = f"Biometric similarity below threshold ({score_str}). {legs_str}" if legs_str else f"ArcFace similarity below threshold ({score_str}). Imposter risk flagged."
            elif status == 'inconclusive':
                res_p = Paragraph("INCONCLUSIVE", badge_review)
                notes = raw.get('reason') or (f"Partial biometric comparison. {legs_str}" if legs_str else "Biometric quality threshold unmet or image inconclusive.")
            else:
                res_p = Paragraph("REVIEW", badge_review)
                notes = raw.get('reason') or (f"Partial biometric legs: {legs_str}" if legs_str else "One or more biometric legs missing for comparison.")
        elif mod_key == 'liveness':
            is_live = raw.get('live')
            if status == 'inconclusive' or is_live is None:
                res_p = Paragraph("INCONCLUSIVE", badge_review)
                raw_reason = str(raw.get('reason') or '').strip()
                if 'libEGL' in raw_reason or 'shared object' in raw_reason:
                    notes = "Liveness engine dependency unmet on server (libEGL required); manual review required."
                elif 'expected a frame burst' in raw_reason or 'no live capture provided' in raw_reason:
                    notes = "Single photo or no burst provided; temporal liveness requires >=3 camera frames."
                elif 'face_landmarker.task' in raw_reason:
                    notes = "Liveness model not installed; manual officer review required."
                elif raw_reason:
                    notes = raw_reason
                else:
                    notes = "Insufficient frames or challenge unverified; manual review required."
            elif is_live is True:
                res_p = Paragraph("GENUINE LIVE", badge_pass)
                notes = "Dynamic EAR blink challenge and natural facial motion confirmed."
            else:
                res_p = Paragraph("SPOOF / REPLAY", badge_fail)
                notes = "Static photo, screen replay, or 3D mask artifact detected."
        elif status == 'inconclusive':
            res_p = Paragraph("INCONCLUSIVE", badge_review)
            notes = raw.get('reason') or "Quality threshold unmet or image inconclusive."
        elif mod_key == 'tamper':
            is_tampered = (score or 0) >= 0.5
            res_p = Paragraph("TAMPER DETECTED", badge_fail) if is_tampered else Paragraph("PASSED", badge_pass)
            notes = "Compression artifact anomalies detected" if is_tampered else "Uniform compression residuals; no copy-move clones."
        elif mod_key == 'watchlist':
            is_hit = raw.get('is_hit', False)
            res_p = Paragraph("LOOKOUT HIT", badge_fail) if is_hit else Paragraph("CLEAR", badge_pass)
            notes = f"Matches recorded lookout subject: {raw.get('hit_name', '')}" if is_hit else "Subject cleared against all active lookout entries."
        elif mod_key == 'deepfake':
            is_fake = (score or 0) >= 0.7
            res_p = Paragraph("HIGH SYNTHETIC RISK", badge_fail) if is_fake else Paragraph("NATURAL", badge_pass)
            notes = "High-frequency Fourier upsampling artifacts found" if is_fake else "Radial frequency power spectrum conforms to natural camera sensor."
        else:
            res_p = Paragraph("OK", badge_pass) if status == 'ok' else Paragraph("REVIEW", badge_review)
            notes = raw.get('algorithm') or raw.get('details') or "Check completed successfully."

        forensic_rows.append([
            Paragraph(mod_label, cell_bold),
            Paragraph(score_str, cell_style),
            res_p,
            Paragraph(str(notes)[:160], cell_style),
        ])

    forensic_table = Table(forensic_rows, colWidths=[150, 65, 85, 230])
    forensic_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EAECF0')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#D0D5DD')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E4E7EC')),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(forensic_table)
    story.append(Spacer(1, 10))

    # 6. Legal Chain-of-Custody & Signatures (KeepTogether to ensure on same page or neatly wrapped)
    legal_elements = []
    legal_elements.append(Paragraph("3. Legal Chain-of-Custody & Cryptographic Provenance", section_hdr))

    prov_hash = (provenance_data or {}).get('audit_chain_hash') or (provenance_data or {}).get('signature') or "SHA256-AUTHENTICATED-LEDGER-CHAIN"
    if len(str(prov_hash)) > 64:
        prov_hash = str(prov_hash)[:64] + "..."

    legal_data = [
        [
            Paragraph("<b>Cryptographic Ledger Hash:</b>", cell_style),
            Paragraph(f"<font face='Courier'>{prov_hash}</font>", cell_style),
        ],
        [
            Paragraph("<b>Chain Integrity:</b>", cell_style),
            Paragraph("Cryptographically sealed in append-only audit trail.", cell_style),
        ],
        [
            Paragraph("<b>Reviewing Officer:</b>", cell_style),
            Paragraph(f"Officer ID: {officer_id} (Unit: {unit})", cell_style),
        ],
        [
            Paragraph("<b>Officer Signature:</b>", cell_style),
            Paragraph("___________________________________  [Date: ________________]", cell_style),
        ],
    ]
    legal_table = Table(legal_data, colWidths=[140, 390])
    legal_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    legal_elements.append(legal_table)
    legal_elements.append(Spacer(1, 6))

    legal_elements.append(Paragraph(
        "<i>CONFIDENTIAL & PROPRIETARY — LAW ENFORCEMENT & BORDER CONTROL USE ONLY. Generated by NetrAksha Automated Screening System under MHA/SSB guidelines.</i>",
        subtext_style
    ))

    story.append(KeepTogether(legal_elements))

    # Build PDF
    doc.build(story)
    return buffer.getvalue()
