"""Knowledge index: init/build/check, Office/PDF/HTML/CSV mirrors, redaction, manual block, freshness."""

import importlib.util
import json
import unittest
import zipfile

from tests._support import make_temp_dir, run_cli, write

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
REL = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def make_zip(path, parts):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)


def paragraph(text, style=""):
    properties = '<w:pPr><w:pStyle w:val="' + style + '"/></w:pPr>' if style else ""
    return f"<w:p>{properties}<w:r><w:t>{text}</w:t></w:r></w:p>"


def cell(text):
    return f"<w:tc>{paragraph(text)}</w:tc>"


def docx(path):
    body = (paragraph("Order spec", "Heading1") + paragraph("Stock must never be negative.")
            + f"<w:tbl><w:tr>{cell('Field')}{cell('Rule')}</w:tr><w:tr>{cell('quantity')}{cell('&gt; 0')}</w:tr></w:tbl>"
            + paragraph("password = hunter2secret"))
    make_zip(path, {"word/document.xml": f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>'})


def xlsx(path):
    make_zip(path, {
        "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="Prices" sheetId="1" r:id="rId1"/>'
                           f'<sheet name="Hidden" sheetId="2" state="hidden" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships {REL}><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="ws"/>'
                                      f'<Relationship Id="rId2" Target="worksheets/sheet2.xml" Type="ws"/></Relationships>',
        "xl/sharedStrings.xml": f"<sst {S}><si><t>SKU</t></si><si><t>Price</t></si></sst>",
        "xl/worksheets/sheet1.xml": (
            f'<worksheet {S}><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>ABC</t></is></c><c r="B2"><v>125000</v></c></row>'
            '<row r="3"><c r="B3"><f>SUM(B2:B2)</f><v>125000</v></c></row>'
            '</sheetData><mergeCells count="1"><mergeCell ref="A3:A4"/></mergeCells></worksheet>'),
        "xl/worksheets/sheet2.xml": f'<worksheet {S}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>internal</t></is></c></row></sheetData></worksheet>',
    })


def pptx(path):
    make_zip(path, {
        "ppt/presentation.xml": f'<p:presentation {P} {R}><p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": f'<Relationships {REL}><Relationship Id="rId2" Target="slides/slide1.xml" Type="slide"/></Relationships>',
        "ppt/slides/slide1.xml": f"<p:sld {P} {A}><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Checkout flow</a:t></a:r></a:p>"
                                 "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>",
    })


def pdf_bytes(text):
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 144] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    output += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    output += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(output)


class KnowledgeIndexTest(unittest.TestCase):
    def setUp(self):
        self.root = make_temp_dir(self)
        write(self.root, "README.md", "# Shop\n")
        write(self.root, "CLAUDE.md", "# Rules\n")
        write(self.root, "docs/spec.md", "# Spec\n\nSee [readme](../README.md).\n\napi_key: 'abcd1234" + "efgh5678'\n")
        write(self.root, "docs/data.csv", "sku,price\nA,1\nB,2\n")
        write(self.root, "docs/page.html", "<h1>Title</h1><p>Para</p><table><tr><td>a</td><td>b</td></tr></table><script>x()</script>")
        write(self.root, "specs/api.yaml", "openapi: 3.1.0\ninfo:\n  title: Shop\n")
        write(self.root, "docs/diagram.png", b"\x89PNG\r\n\x1a\nfake")
        write(self.root, "docs/.env", "SECRET=should-not-appear\n")
        docx(self.root / "docs/design.docx")
        xlsx(self.root / "docs/prices.xlsx")
        pptx(self.root / "docs/flow.pptx")
        (self.root / "docs/manual.pdf").write_bytes(pdf_bytes("Hello PDF page"))

    def knowledge(self, *args):
        return run_cli("knowledge", *args, "--repo", str(self.root))

    def mirror(self, relative):
        return (self.root / ".knowledge" / "mirrors" / relative).read_text(encoding="utf-8")

    def test_init_build_check_cycle(self):
        init = self.knowledge("init", "--language", "vi", "--title", "Shop Knowledge")
        self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
        self.assertIn("CURRENT", init.stdout)
        index = (self.root / ".knowledge" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("# Shop Knowledge", index)
        self.assertIn("Việc cần làm trước", index)
        self.assertIn("mirrors/docs/design.docx.md", index)
        self.assertIn("docs/diagram.png", index, "non-convertible files are listed as not converted")
        self.assertNotIn(".env", index.replace(".env.example", ""))

        docx_mirror = self.mirror("docs/design.docx.md")
        self.assertIn("## Order spec", docx_mirror)
        self.assertIn("<!-- ¶2 -->", docx_mirror)
        self.assertIn("| quantity | > 0 |", docx_mirror)
        self.assertNotIn("hunter2secret", docx_mirror)
        xlsx_mirror = self.mirror("docs/prices.xlsx.md")
        self.assertIn("## Sheet: Hidden (hidden)", xlsx_mirror)
        self.assertIn("| 2 | ABC | 125000 |", xlsx_mirror)
        self.assertIn("B3: `=SUM(B2:B2)`", xlsx_mirror)
        data = json.loads((self.root / ".knowledge" / "data" / "docs/prices.xlsx.json").read_text())
        self.assertEqual(data["sheets"][0]["merged"], ["A3:A4"])
        self.assertIn("Checkout flow", self.mirror("docs/flow.pptx.md"))
        self.assertIn("| 2 | B | 2 |", self.mirror("docs/data.csv.md"))
        html_mirror = self.mirror("docs/page.html.md")
        self.assertIn("## Title", html_mirror)
        self.assertIn("| a | b |", html_mirror)
        self.assertNotIn("x()", html_mirror)
        spec_mirror = self.mirror("docs/spec.md")
        self.assertIn("(../../../README.md)", spec_mirror, "relative links point back at the originals")
        self.assertNotIn("abcd1234efgh5678", spec_mirror)
        self.assertIn("```yaml", self.mirror("specs/api.yaml.md"))
        if importlib.util.find_spec("pypdf"):
            self.assertIn("Hello PDF page", self.mirror("docs/manual.pdf.md"))
        else:
            self.assertIn("pypdf", index)

    def test_manual_block_and_freshness(self):
        self.assertEqual(self.knowledge("init").returncode, 0)
        index_path = self.root / ".knowledge" / "INDEX.md"
        text = index_path.read_text(encoding="utf-8")
        start, end = "<!-- knowledge:manual:start -->", "<!-- knowledge:manual:end -->"
        edited = text.split(start)[0] + start + "\n## Reading order\n\n1. docs/design.docx is authoritative.\n" + end + text.split(end)[1]
        index_path.write_text(edited, encoding="utf-8")
        check = self.knowledge("check")
        self.assertEqual(check.returncode, 0, check.stdout)
        self.assertIn("CURRENT", check.stdout)

        write(self.root, "docs/spec.md", "# Spec v2\n")
        stale = self.knowledge("check")
        self.assertIn("STALE", stale.stdout)
        self.assertIn("source changed: docs/spec.md", stale.stdout)
        write(self.root, "docs/new.md", "# New\n")
        self.assertIn("new source: docs/new.md", self.knowledge("check").stdout)

        self.assertEqual(self.knowledge("build").returncode, 0)
        self.assertIn("CURRENT", self.knowledge("check").stdout)
        self.assertIn("docs/design.docx is authoritative", index_path.read_text(encoding="utf-8"))

        (self.root / ".knowledge" / "mirrors" / "docs" / "spec.md").write_text("tampered", encoding="utf-8")
        self.assertIn("generated file edited", self.knowledge("check").stdout)

    def test_check_without_index_is_blocked(self):
        completed = run_cli("knowledge", "check", "--repo", str(make_temp_dir(self)))
        self.assertEqual(completed.returncode, 4)
        self.assertEqual(run_cli("knowledge", "init", "--repo", str(make_temp_dir(self))).returncode, 2,
                         "nothing to index is a usage error")


if __name__ == "__main__":
    unittest.main()
